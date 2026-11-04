"""Prepare a fresh copied official f34 fixture and empty comparison destinations."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from ..paths import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    checkout = ROOT / "upstream/Delft3D"
    source = checkout / "examples/dflowfm/01_dflowfm_sequential/dflowfm"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, out / "source-input")
    for folder in ["gui-project", "gui-export-1", "gui-export-2", "console-export-1", "console-export-2", "working", "snapshots"]:
        (out / folder).mkdir()
    record = {"prepared_at_utc": datetime.now(timezone.utc).isoformat(), "source": str(source),
              "source_commit": subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip(),
              "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.iterdir()) if p.is_file()},
              "purpose": "Project save/export comparison; no simulation execution"}
    (out / "fixture.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps({"experiment": str(out), "input_files": len(record["files"])}))


if __name__ == "__main__":
    main()
