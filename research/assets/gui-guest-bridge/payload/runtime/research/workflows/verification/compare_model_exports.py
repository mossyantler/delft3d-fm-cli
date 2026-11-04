"""Compare two export folders without rewriting them; check known FM input links.

MDU comparison retains repeated keys and distinguishes key/value changes from
text/header changes. This is experiment analysis, not full model validation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import difflib
import hashlib
import json
from pathlib import Path
import re


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entries(path: Path) -> dict:
    section = ""
    result = defaultdict(list)
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().casefold()
        elif "=" in line:
            key, value = line.split("=", 1)
            result[f"{section}/{key.strip().casefold()}"].append({"value": value.strip(), "line": number})
    return dict(result)


def numeric_equal(a: str, b: str) -> bool:
    try:
        return Decimal(a.replace("D", "e").replace("d", "e")) == Decimal(b.replace("D", "e").replace("d", "e"))
    except InvalidOperation:
        return False


def mdu_changes(a: Path, b: Path) -> dict:
    left, right = entries(a), entries(b)
    changes, numeric_format = {}, {}
    for key in sorted(left.keys() & right.keys()):
        av = [v["value"] for v in left[key]]
        bv = [v["value"] for v in right[key]]
        if av != bv:
            target = numeric_format if len(av) == len(bv) and all(x == y or numeric_equal(x, y) for x, y in zip(av, bv)) else changes
            target[key] = {"before": left[key], "after": right[key]}
    return {"added_keys": {k: right[k] for k in sorted(right.keys()-left.keys())},
            "removed_keys": {k: left[k] for k in sorted(left.keys()-right.keys())},
            "value_changes": changes, "numeric_format_changes": numeric_format,
            "scope": "MDU section/key/value comparison; no inferred physical equivalence"}


def references(root: Path) -> dict:
    mdus = list(root.glob("*.mdu"))
    reports = []
    known_keys = {"geometry/netfile", "geometry/thindamfile", "geometry/drypointsfile",
                  "geometry/landboundaryfile", "geometry/inifieldfile", "geometry/structurefile",
                  "external forcing/extforcefile", "external forcing/extforcefilenew",
                  "output/obsfile", "output/crsfile", "restart/restartfile"}
    for mdu in mdus:
        fields = entries(mdu)
        mode = fields.get("general/pathsrelativetoparent", [{"value": "0"}])[0]["value"]
        for key in sorted(known_keys & fields.keys()):
            for entry in fields[key]:
                value = entry["value"]
                if not value:
                    continue
                path = mdu.parent / value
                reports.append({"from": mdu.name, "key": key, "value": value, "exists": path.is_file(),
                                "inside_folder": path.resolve().is_relative_to(root.resolve())})
                if path.suffix.casefold() == ".ext" and path.is_file():
                    for extkey, values in entries(path).items():
                        if extkey.rsplit("/", 1)[-1] in {"locationfile", "forcingfile"}:
                            for extentry in values:
                                base = path.parent if mode == "1" else mdu.parent
                                target = base / extentry["value"]
                                reports.append({"from": path.name, "key": extkey, "value": extentry["value"],
                                                "exists": target.is_file(), "inside_folder": target.resolve().is_relative_to(root.resolve())})
    return {"mdus": [p.name for p in mdus], "links": reports,
            "known_links_resolve_inside_folder": bool(reports) and all(r["exists"] and r["inside_folder"] for r in reports),
            "scope": "Known MDU and new-style EXT path fields only; no complete schema/BC identity/native validation"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    before, after = args.before.resolve(strict=True), args.after.resolve(strict=True)
    args.out.mkdir(parents=True, exist_ok=False)
    left = {p.relative_to(before).as_posix(): p for p in before.rglob("*") if p.is_file()}
    right = {p.relative_to(after).as_posix(): p for p in after.rglob("*") if p.is_file()}
    common = left.keys() & right.keys()
    changed = [k for k in sorted(common) if digest(left[k]) != digest(right[k])]
    report = {"before": str(before), "after": str(after),
              "added": sorted(right.keys()-left.keys()), "removed": sorted(left.keys()-right.keys()),
              "byte_identical": [k for k in sorted(common) if k not in changed], "changed": changed,
              "mdu_changes": {}, "before_references": references(before), "after_references": references(after)}
    for key in changed:
        if Path(key).suffix.casefold() in {".mdu", ".ext", ".bc", ".pli", ".xyn", ".xyz", ".wnd"}:
            delta = "\n".join(difflib.unified_diff(left[key].read_text(encoding="utf-8-sig").splitlines(),
                                                 right[key].read_text(encoding="utf-8-sig").splitlines(),
                                                 fromfile="before/"+key, tofile="after/"+key, lineterm=""))
            (args.out / (key.replace("/", "_") + ".diff")).write_text(delta+"\n", encoding="utf-8")
        if key.endswith(".mdu"):
            report["mdu_changes"][key] = mdu_changes(left[key], right[key])
    (args.out / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
