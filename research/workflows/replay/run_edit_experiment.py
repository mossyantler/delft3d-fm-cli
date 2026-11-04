"""Replay E003/E005 sequentially on three independent copies of the f34 project."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from ..verification.snapshot import snapshot, compare

from ..paths import ROOT


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="Folder with gui-baseline.dsproj and its companion data")
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    baseline = args.baseline.resolve(strict=True)
    assert (baseline / "gui-baseline.dsproj").is_file()
    assert (baseline / "gui-baseline.dsproj_data/f34/input/f34.mdu").is_file()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "snapshots").mkdir()
    before = snapshot(baseline, out / "snapshots/original-baseline-before.json")
    write(out / "snapshots/original-baseline-before.json", before)
    write(out / "fixture.json", {"source_project": str(baseline), "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
          "cases": ["control", "scalar", "boundary"], "execution": "sequential",
          "script_sha256": hashlib.sha256((ROOT / "assets/edit-experiment/export_case.py").read_bytes()).hexdigest(),
          "scalar_intended": {"key": "output/HisInterval", "before": 300, "after": 600, "unit": "s"},
          "boundary_intended": {"name": "L1_0001", "period_minutes": 750, "component": "amplitude", "before": 1.5, "after": 1.75, "unit": "m"}})
    for name in ["control", "scalar", "boundary"]:
        case = out / name
        case.mkdir()
        shutil.copytree(baseline, case / "project")
        for folder in ["export-1", "export-2"]:
            (case / folder).mkdir()
        write(case / "case.json", {"case": name})
        case_before = snapshot(case / "project", out / "snapshots" / f"{name}-project-before.json")
        write(out / "snapshots" / f"{name}-project-before.json", case_before)
        command = [sys.executable, str(ROOT / "scripts/run_shell_script.py"), "--install", str(args.install.resolve(strict=True)),
                   "--script", str(ROOT / "assets/edit-experiment/export_case.py"), "--experiment-root", str(case),
                   "--out", str(case / "run"), "--timeout", "45"]
        subprocess.run(command, check=True)
        case_after = snapshot(case / "project", out / "snapshots" / f"{name}-project-after.json")
        write(out / "snapshots" / f"{name}-project-after.json", case_after)
        write(out / "snapshots" / f"{name}-project-diff.json", compare(case_before, case_after))
        print(f"Completed {name}", flush=True)
    after = snapshot(baseline, out / "snapshots/original-baseline-after.json")
    write(out / "snapshots/original-baseline-after.json", after)
    write(out / "snapshots/original-baseline-diff.json", compare(before, after))
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_edit_experiment.py"), str(out)], check=True)


if __name__ == "__main__":
    main()
