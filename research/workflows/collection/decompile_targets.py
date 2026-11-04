"""Read selected GUI integration types with ILSpyCmd; keep output local/private."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from ..paths import ROOT
TARGETS = {
    "DimrRunner": ("DeltaShell.Dimr", "DeltaShell.Dimr.DimrRunner"),
    "DimrApi": ("DeltaShell.Dimr", "DeltaShell.Dimr.DimrApi"),
    "RemoteDimrApi": ("DeltaShell.Dimr", "DeltaShell.Dimr.RemoteDimrApi"),
    "DimrApiFactory": ("DeltaShell.Dimr", "DeltaShell.Dimr.DimrApiFactory"),
    "DimrApiDataSet": ("DeltaShell.Dimr", "DeltaShell.Dimr.DimrApiDataSet"),
    "FMModelFileExporter": ("DeltaShell.Plugins.FMSuite.FlowFM", "DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters.FMModelFileExporter"),
    "FMModelPartitionExporter": ("DeltaShell.Plugins.FMSuite.FlowFM", "DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters.FMModelPartitionExporter"),
    "BcFileBoundaryExporter": ("DeltaShell.Plugins.FMSuite.FlowFM", "DeltaShell.Plugins.FMSuite.FlowFM.IO.ImportExport.Exporters.BcFileBoundaryExporter"),
    "ScriptHost": ("DeltaShell.Plugins.Scripting", "DeltaShell.Plugins.Scripting.ScriptHost"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--target", choices=list(TARGETS), action="append")
    args = parser.parse_args()
    acquisition = json.loads((ROOT / "evidence/acquisition/managed-cli.json").read_text(encoding="utf-8"))
    output = ROOT / "evidence" / "managed-inspection"
    output.mkdir(parents=True, exist_ok=True)
    dependencies = [args.install / "bin", *[p for p in (args.install / "plugins").iterdir() if p.is_dir()]]
    manifest = output / "manifest.json"
    report = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    for name in args.target or TARGETS:
        plugin, typename = TARGETS[name]
        assembly = args.install / "plugins" / plugin / f"{plugin}.dll"
        command = [*acquisition["command"], "--disable-updatecheck", "-t", typename]
        for directory in dependencies:
            command.extend(["-r", str(directory)])
        command.append(str(assembly))
        result = subprocess.run(command, capture_output=True, timeout=90)
        (output / f"{name}.cs").write_bytes(result.stdout)
        (output / f"{name}.stderr.txt").write_bytes(result.stderr)
        report[name] = {"assembly": str(assembly), "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest(),
                        "type": typename, "command": command, "returncode": result.returncode,
                        "stdout_bytes": len(result.stdout), "stderr_bytes": len(result.stderr)}
        (output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{name}: exit={result.returncode}, output={len(result.stdout)} bytes, stderr={len(result.stderr)} bytes", flush=True)
    if any(r["returncode"] for r in report.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
