"""Independent fixed06 source/stage recipe oracle, with no product imports."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from .verify_water_quality_offline import BASE, PIN, audit_chain, safe_reference, uncomment
from .verify_water_quality_outputs import require, sha

SOURCE_DIGEST = "a62741ee093a0c4295be0ca431c550ba6706d7d78b2e4742ca76e3ab8fd147ef"


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def duration_token(value):
    require(value.isdigit() and len(value) <= 8, "Invalid ddhhmmss duration")
    value = value.zfill(8)
    days, hours, minutes, seconds = [int(value[i:i+2]) for i in range(0, 8, 2)]
    require(hours < 24 and minutes < 60 and seconds < 60, "Invalid duration clock fields")
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def constants(raw):
    """Tokenize explicit CONSTANTS/DATA names and values, preserving line IDs."""
    lines = raw.decode("ascii").splitlines(keepends=True)
    code = [uncomment(line).strip() for line in lines]
    start = [i for i, line in enumerate(code) if line == "CONSTANTS"]
    require(len(start) == 1, "Require one CONSTANTS block")
    data = next(i for i in range(start[0] + 1, len(code)) if code[i] == "DATA")
    stop = next(i for i in range(data + 1, len(code)) if code[i] == "PARAMETERS")
    names, values = [], []
    for i in range(start[0] + 1, data):
        if code[i]:
            found = re.fullmatch("'([^']+)'", code[i])
            require(found is not None, "Unsupported constant-name syntax")
            names.append((found[1], i))
    for i in range(data + 1, stop):
        if code[i]:
            require(re.fullmatch(r"[+\-\d.eEdD]+", code[i]), "Unsupported constant value syntax")
            values.append((float(code[i].replace("D", "E").replace("d", "e")), i))
    require(len(names) == len(values) and len({name for name, _ in names}) == len(names), "Duplicate/missing explicit constant values")
    return {name: {"value": value, "name_line": ni, "value_line": vi}
            for (name, ni), (value, vi) in zip(names, values)}


def input_recipe(original, prepared, role, duration=3600):
    """Undo only four new common-constant lines and the declared scalar tokens."""
    require(role in ("positive", "control"), "Unknown offline case role")
    require(600 <= duration <= 3600 and duration % 300 == 0, "Unsupported bounded duration")
    before, after = constants(original), constants(prepared)
    require(set(after) == set(before) | {"TcMrtEColi", "CTMrtEColi"}, "Unexpected constant added/removed")
    rate = .8 if role == "positive" else 0.
    for name, entry in after.items():
        expected = {"RcMrtEColi": rate, "TcMrtEColi": 1.07, "CTMrtEColi": 2.}.get(name, before.get(name, {}).get("value"))
        require(entry["value"] == expected, f"Wrong physical constant: {name}")
    remove = {after[name][key] for name in ("TcMrtEColi", "CTMrtEColi") for key in ("name_line", "value_line")}
    lines = [line for i, line in enumerate(prepared.splitlines(keepends=True)) if i not in remove]
    old_lines = original.splitlines(keepends=True)
    require(len(lines) == len(old_lines), "Unexpected INP line insertion/removal")
    stop = (datetime(1990, 8, 5, 12, 30) + timedelta(seconds=duration)).strftime("%Y/%m/%d-%H:%M:%S").encode()
    changed = {}
    for number, (old, new) in enumerate(zip(old_lines, lines), 1):
        if old == new:
            continue
        comment = old.partition(b";")[2].strip().decode("ascii")
        old_code, new_code = old.partition(b";")[0], new.partition(b";")[0]
        tokens = list(re.finditer(rb"\S+", old_code)); actual = list(re.finditer(rb"\S+", new_code))
        require(len(tokens) == len(actual), "Unexpected INP scalar count change")
        edits = {}
        if comment == "stop time":
            require(actual[0][0] == stop, "Quality stop exceeds/differs from declared window")
            edits[0] = actual[0][0]
        elif comment == "time step":
            require(duration_token(actual[0][0].decode()) == 60, "Actual integration step must be60s")
            edits[0] = actual[0][0]
        elif comment in ("monitoring", "map, dump", "history"):
            require(actual[0][0] == b"1990/08/05-12:30:00" and actual[1][0] == stop and
                    duration_token(actual[2][0].decode()) == 300, "Output timer does not cover exact300s cadence")
            edits = {1: actual[1][0], 2: actual[2][0]}
        elif comment == "RcMrtEColi":
            require(float(actual[0][0]) == rate, "Physical case role differs")
            edits[0] = actual[0][0]
        else:
            require(False, f"Unrelated input bytes changed at source line{number}")
        expected = old
        for index, value in sorted(edits.items(), reverse=True):
            token = tokens[index]
            expected = expected[:token.start()] + value + expected[token.end():]
        require(new == expected, f"Non-target whitespace/comment bytes changed at source line{number}")
        changed[comment] = number
    # For positive .8, the rate spelling can legitimately remain the original.
    required = {"stop time", "time step", "monitoring", "map, dump", "history"}
    require(required <= changed.keys(), "Missing bounded clock edits")
    return {"state": "passed_independent_recipe", "role": role, "RcMrtEColi_per_day": rate,
            "Temp_C": after["Temp"]["value"], "TcMrtEColi": 1.07, "CTMrtEColi_C": 2,
            "source_lines_changed": changed, "common_lines_added": len(remove),
            "all_non_target_original_bytes": "preserved", "stop": stop.decode(), "timezone": "not_encoded_in_source"}


def stage_pair(bundle, originals, database):
    """Validate31 actual native files per role plus a self-contained receipt."""
    require(len(originals) == 28 and canonical({name: hashlib.sha256(raw).hexdigest() for name, raw in originals.items()}) == SOURCE_DIGEST,
            "Source is not the exact pinned28 blob graph")
    expected = set(originals) | {"provenance/original.inp", "process_library/proc_def.dat", "process_library/proc_def.def"}
    report, pair = {}, {}
    for role in ("positive", "control"):
        root = Path(bundle) / role
        receipt_path = root / "waq-offline-case.json"
        receipt = json.loads(receipt_path.read_text())
        binding = {key: value for key, value in receipt.items() if key not in ("created_at_utc", "prepared_sha256")}
        require(canonical(binding) == receipt["prepared_sha256"] and receipt["role"] == role and receipt["source_commit"] == PIN, "Invalid role/preparation receipt")
        require({p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} == expected | {receipt_path.name}, "Incomplete/unexpected actual stage graph")
        seen = set()
        for item in receipt["files"]:
            name = item["relative_path"]
            require(name not in seen and name in expected, "Duplicate/escaping/unknown stage inventory")
            seen.add(name)
            path = safe_reference(root, name)
            require(sha(path) == item["sha256"] and path.stat().st_size == item["bytes"], "Stale actual staged input")
        require(seen == expected, "Missing stage receipt member")
        for name, raw in originals.items():
            actual = safe_reference(root, name).read_bytes()
            if name == BASE + ".inp":
                recipe = input_recipe(raw, actual, role)
                pair[role] = actual
            else:
                require(actual == raw, f"Pinned hydro/reference bytes changed: {name}")
        require(safe_reference(root, "provenance/original.inp").read_bytes() == originals[BASE + ".inp"], "Retained original input changed")
        for name, raw in database.items():
            require(safe_reference(root, "process_library/" + name).read_bytes() == raw, "Process database differs from selected resource")
        graph = audit_chain(root)
        require(graph["quality_inside_actual_hydro_range"], "Quality clock falls outside actual hydrodynamic data")
        report[role] = {"recipe": recipe, "graph": graph, "prepared_sha256": receipt["prepared_sha256"],
                        "receipt_sha256": sha(receipt_path), "native_files": len(expected)}
    def normalized(raw):
        lines = raw.splitlines(keepends=True)
        values = constants(raw)["RcMrtEColi"]
        i = values["value_line"]
        lines[i] = re.sub(rb"[+\-\d.eE]+", b"ROLE_RATE", lines[i], count=1)
        return b"".join(lines)
    require(normalized(pair["positive"]) == normalized(pair["control"]), "Pair differs beyond the sole mortality rate")
    return report
