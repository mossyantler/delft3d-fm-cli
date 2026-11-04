"""Build a compact static MDU evidence registry, never a support declaration.

Only literal prop_get*/prop_set calls in the locked primary MDU reader/writer
and direct HYDROLIB MDU model fields are indexed. Dynamic keys, other readers,
GUI ownership and actual engine behavior are not inferred from this index.
Run intentionally with --out src/dfm_cli/fields_registry.json to refresh it.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

ENGINE_FILE = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90"
HYDRO_FILE = "hydrolib/core/dflowfm/mdu/models.py"


def cleaned_fortran(text):
    """Blank comments/continuation markers while preserving source offsets."""
    chars, quote, index = list(text), None, 0
    while index < len(chars):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(chars) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "!":
            while index < len(chars) and text[index] != "\n":
                chars[index] = " "
                index += 1
            continue
        elif char == "&":
            chars[index] = " "
        index += 1
    return "".join(chars)


def call_arguments(text, opening):
    """Split the complete call, never comma-split a nested function/string."""
    args, start, depth, bracket_depth, quote, i = [], opening + 1, 1, 0, None, opening + 1
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(": depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                args.append(text[start:i].strip())
                return args, i + 1
        elif char == "[": bracket_depth += 1
        elif char == "]": bracket_depth -= 1
        elif char == "," and depth == 1 and bracket_depth == 0:
            args.append(text[start:i].strip())
            start = i + 1
        i += 1
    raise ValueError("Unterminated property call at source offset " + str(opening))


def literal(token):
    for quote in ("'", '"'):
        match = re.fullmatch(re.escape(quote) + "((?:[^" + quote + "]|" + quote * 2 + ")*)" + re.escape(quote), token)
        if match:
            return match[1].replace(quote * 2, quote)
    return None


def engine_records(text):
    cleaned = cleaned_fortran(text)
    pattern = re.compile(r"\bcall\s+(prop_get(?:_[a-z0-9_]+)?|prop_set)\s*\(", re.I)
    records = defaultdict(lambda: {"read": [], "write": [], "symbols": []})
    i, quote = 0, None
    while i < len(cleaned):
        char = cleaned[i]
        if quote:
            if char == quote:
                if i + 1 < len(cleaned) and cleaned[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if char in "'\"":
            quote = char
            i += 1
            continue
        match = pattern.match(cleaned, i) if char.casefold() == "c" else None
        if match is None:
            i += 1
            continue
        args, i = call_arguments(cleaned, match.end() - 1)
        if len(args) < 4:
            raise ValueError("Property call needs at least four arguments")
        section, key = literal(args[1]), literal(args[2])
        if section is None or key is None or not section.strip() or not key.strip():
            continue  # Dynamic names remain outside the literal index.
        address = section.strip().casefold() + "/" + key.strip().casefold()
        record = records[address]
        record["read" if match[1].casefold().startswith("prop_get") else "write"].append(cleaned.count("\n", 0, match.start()) + 1)
        symbol = " ".join(line.strip() for line in args[3].splitlines()).strip()
        if symbol not in record["symbols"]:
            record["symbols"].append(symbol)
    return dict(records)


def hydrolib_records(text):
    result = {}
    for cls in ast.parse(text).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        header = next((n.value.value for n in cls.body if isinstance(n, ast.AnnAssign)
                       and isinstance(n.target, ast.Name) and n.target.id == "_header"
                       and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)), None)
        if not header:
            continue
        comments = {}
        for nested in cls.body:
            if not isinstance(nested, ast.ClassDef) or nested.name != "Comments":
                continue
            for node in nested.body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and isinstance(node.value, ast.Call):
                    if node.value.args and isinstance(node.value.args[0], ast.Constant) and isinstance(node.value.args[0].value, str):
                        comments[node.target.id] = {"comment": node.value.args[0].value, "comment_line": node.lineno}
        for node in cls.body:
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name) or not isinstance(node.value, ast.Call):
                continue
            aliases = [kw.value.value for kw in node.value.keywords if kw.arg == "alias" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)]
            if not aliases:
                continue
            alias = aliases[0]
            result[header.casefold() + "/" + alias.casefold()] = {
                "class": cls.name, "attribute": node.target.id, "alias": alias,
                "type": ast.unparse(node.annotation), "line": node.lineno, **comments.get(node.target.id, {})}
    return result


def locked_file(root, relative, commit):
    path = root / relative
    actual = path.read_bytes()
    reference = subprocess.run(["git", "-C", str(root), "show", commit + ":" + relative], capture_output=True, check=True).stdout
    if actual.replace(b"\r\n", b"\n") != reference.replace(b"\r\n", b"\n"):
        raise ValueError("Reference file differs from the acquisition lock: " + str(path))
    # Parse the exact pinned blob. sha256 remains the separately verified
    # checkout-artifact fingerprint for backward-compatible provenance.
    return reference, hashlib.sha256(actual).hexdigest(), hashlib.sha256(reference).hexdigest()


def build(engine_root, hydro_root, lock):
    engine_commit = lock["repositories"]["Delft3D"]["commit"]
    hydro_commit = lock["repositories"]["HYDROLIB-core"]["commit"]
    engine, engine_hash, engine_blob_hash = locked_file(engine_root, ENGINE_FILE, engine_commit)
    hydro, hydro_hash, hydro_blob_hash = locked_file(hydro_root, HYDRO_FILE, hydro_commit)
    native, typed = engine_records(engine.decode("utf-8-sig")), hydrolib_records(hydro.decode("utf-8-sig"))
    records = {}
    for address in sorted(native.keys() | typed.keys()):
        records[address] = {}
        if address in native: records[address]["engine"] = native[address]
        if address in typed: records[address]["hydrolib"] = typed[address]
    return {"schema_version": 1,
            "classification": "static source index; not engine validation, GUI observation or supported-edit schema",
            "coverage": "Literal keys in the primary MDU reader/writer plus direct HYDROLIB MDU model fields; other readers/dynamic keys unindexed",
            "installed_engine_source_revision": "unknown",
            "sources": {"engine": {"repository": "Deltares/Delft3D", "commit": engine_commit, "path": ENGINE_FILE, "sha256": engine_hash, "git_blob_sha256": engine_blob_hash},
                        "hydrolib": {"repository": "Deltares/HYDROLIB-core", "commit": hydro_commit, "path": HYDRO_FILE, "sha256": hydro_hash, "git_blob_sha256": hydro_blob_hash}},
            "records": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, default=Path("research/upstream/Delft3D"))
    parser.add_argument("--hydrolib-root", type=Path, default=Path("research/upstream/HYDROLIB-core"))
    parser.add_argument("--lock", type=Path, default=Path("research/sources.lock.json"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    data = build(args.engine_root, args.hydrolib_root, json.loads(args.lock.read_text(encoding="utf-8")))
    # One evidence record per line makes acquisition changes reviewable.
    metadata = {k: v for k, v in data.items() if k != "records"}
    text = json.dumps(metadata, indent=2, ensure_ascii=False)[:-2] + ',\n  "records": {\n'
    text += ",\n".join("    " + json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False, sort_keys=True) for k, v in data["records"].items())
    text += "\n  }\n}\n"
    json.loads(text)  # Verify the compact serializer before publication.
    args.out.write_text(text, encoding="utf-8", newline="")
    print(json.dumps({"records": len(data["records"]), "out": str(args.out), "sources": data["sources"]}, indent=2))


if __name__ == "__main__":
    main()
