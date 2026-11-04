"""Verify exact E003/E005 deltas, repeated exports, references, and unchanged inputs.

The BC parser is deliberately scoped to the harmonic f34 fixture. It retains
ordered metadata/repeated blocks and checks every numeric cell, not just INI keys.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from .compare_model_exports import entries, mdu_changes, references
from .snapshot import snapshot, compare

from ..paths import ROOT


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_bc(path: Path) -> list[dict]:
    blocks = []
    for number, raw in enumerate(path.read_bytes().decode("utf-8-sig").splitlines(keepends=True), 1):
        line = raw.split("#", 1)[0].strip()
        header = re.fullmatch(r"\[([^]]+)\]", line)
        if header:
            blocks.append({"section": header[1].casefold(), "metadata": [], "rows": [], "row_lines": [], "raw": []})
        if not blocks:
            assert not line
            continue
        block = blocks[-1]
        block["raw"].append(raw)
        if not line or header:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            block["metadata"].append([key.strip().casefold(), value.strip()])
        else:
            block["rows"].append(line.split())
            block["row_lines"].append(number)
    return blocks


def forcing_name(block: dict) -> str:
    names = [value for key, value in block["metadata"] if key == "name"]
    assert len(names) == 1
    return names[0]


def field_changes(change: dict) -> None:
    assert not change["added_keys"] and not change["removed_keys"]
    assert not change["numeric_format_changes"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--scalar-case", default="scalar")
    args = parser.parse_args()
    root = args.experiment.resolve(strict=True)
    analysis = root / "analysis"
    analysis.mkdir(exist_ok=False)
    cases = {"control": root / "control", "scalar": root / args.scalar_case, "boundary": root / "boundary"}
    results = {name: json.loads((case / "edit-result.json").read_text()) for name, case in cases.items()}
    assert all(result["success"] for result in results.values())
    exported = {name: case / "export-1" for name, case in cases.items()}
    controls = entries(exported["control"] / "f34.mdu")
    assert [x["value"] for x in controls["output/hisinterval"]] == ["300"]
    changes = mdu_changes(exported["control"] / "f34.mdu", exported["scalar"] / "f34.mdu")
    field_changes(changes)
    assert set(changes["value_changes"]) == {"output/hisinterval"}
    actual = changes["value_changes"]["output/hisinterval"]
    assert [x["value"] for x in actual["before"]] == ["300"]
    assert [x["value"] for x in actual["after"]] == ["600"]
    boundary_mdu = mdu_changes(exported["control"] / "f34.mdu", exported["boundary"] / "f34.mdu")
    field_changes(boundary_mdu)
    assert not boundary_mdu["value_changes"]
    expected_names = sorted(p.name for p in exported["control"].iterdir() if p.is_file())
    assert len(expected_names) == 10
    case_summaries = {}
    for name, folder in exported.items():
        assert sorted(p.name for p in folder.iterdir() if p.is_file()) == expected_names
        changed_files = [file for file in expected_names if digest(exported["control"] / file) != digest(folder / file)]
        intended = {"control": set(), "scalar": {"f34.mdu"}, "boundary": {"f34.mdu", "f34_001.bc"}}[name]
        assert set(changed_files) <= intended
        if name == "boundary":
            assert "f34_001.bc" in changed_files
        links = references(folder)
        assert links["known_links_resolve_inside_folder"] and len(links["links"]) == 9
        repeat = cases[name] / "export-2"
        repeat_mdu = mdu_changes(folder / "f34.mdu", repeat / "f34.mdu")
        field_changes(repeat_mdu)
        assert not repeat_mdu["value_changes"]
        assert all(digest(folder / file) == digest(repeat / file) for file in expected_names if file != "f34.mdu")
        case_summaries[name] = {"changed_files_vs_control": changed_files, "known_references_resolved": 9,
                                "repeat_non_mdu_files_identical": 9, "repeat_mdu_value_changes": 0}
        for label, left, right in [(f"{name}-repeat", folder, repeat)]:
            subprocess.run([sys.executable, str(ROOT / "scripts/compare_model_exports.py"), str(left), str(right),
                            "--out", str(analysis / label)], check=True, capture_output=True)
    before = read_bc(exported["control"] / "f34_001.bc")
    after = read_bc(exported["boundary"] / "f34_001.bc")
    assert len(before) == len(after) == 4
    assert [forcing_name(b) for b in before if b["section"] == "forcing"] == ["L1_0001", "L1_0007", "L1_0013"]
    bc_delta = []
    for block_index, (left, right) in enumerate(zip(before, after)):
        assert left["section"] == right["section"] and left["metadata"] == right["metadata"]
        assert len(left["rows"]) == len(right["rows"])
        if block_index != 1:
            assert left["raw"] == right["raw"]
        for row_index, (a, b) in enumerate(zip(left["rows"], right["rows"])):
            assert len(a) == len(b)
            for column, (x, y) in enumerate(zip(a, b)):
                if Decimal(x) != Decimal(y):
                    bc_delta.append({"name": forcing_name(left), "row_zero_based": row_index, "column_zero_based": column,
                                     "period_minutes": a[0], "before": x, "after": y,
                                     "before_line": left["row_lines"][row_index], "after_line": right["row_lines"][row_index]})
    assert len(bc_delta) == 1
    delta = bc_delta[0]
    assert {k: delta[k] for k in ["name", "period_minutes", "column_zero_based", "before", "after"]} == {
        "name": "L1_0001", "period_minutes": "750", "column_zero_based": 1, "before": "1.5", "after": "1.75"}
    assert read_bc(exported["scalar"] / "f34_001.bc") == before
    # Verify the sparse support labels against the unchanged PLI, without inferring snapping.
    pli = (exported["control"] / "f34_001.pli").read_text().splitlines()
    assert pli[0].strip() == "L1" and pli[1].split() == ["13", "2"]
    labels = [row.split()[2] for row in pli[2:] if row.strip()]
    assert len(labels) == 13 and [labels[i] for i in [0, 6, 12]] == ["L1_0001", "L1_0007", "L1_0013"]
    for name in ["scalar", "boundary"]:
        subprocess.run([sys.executable, str(ROOT / "scripts/compare_model_exports.py"), str(exported["control"]), str(exported[name]),
                        "--out", str(analysis / f"control-vs-{name}")], check=True, capture_output=True)
    project_diffs = {}
    for name, case in cases.items():
        prefix = case.name
        old = json.loads((root / "snapshots" / f"{prefix}-project-before.json").read_text())
        current = snapshot(case / "project", analysis / f"{name}-project-after.json")
        project_diffs[name] = compare(old, current)
        assert current["complete"] and all(not project_diffs[name][key] for key in ["added", "removed", "content_changed", "metadata_only"])
    old = json.loads((root / "snapshots/original-baseline-before.json").read_text())
    current = snapshot(Path(old["root"]), analysis / "original-baseline-after.json")
    original_diff = compare(old, current)
    assert current["complete"] and all(not original_diff[key] for key in ["added", "removed", "content_changed", "metadata_only"])
    report = {"status": "passed", "experiment": root.name, "scalar_change": actual, "boundary_numeric_changes": bc_delta,
              "cases": case_summaries, "metadata_and_units_preserved": True, "non_target_bc_blocks_byte_identical": True,
              "sparse_support_names": [labels[i] for i in [0, 6, 12]], "original_baseline_unchanged": True,
              "copied_projects_unchanged": project_diffs, "scope": "Application API edits/export comparison, not interactive UI or simulation validation"}
    (root / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
