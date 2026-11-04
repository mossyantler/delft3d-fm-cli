"""Read-only installation inventory, PE/CLR inspection, and engine help probes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import pefile
import dnfile

from ..paths import ROOT


def binary_info(path: Path) -> dict:
    data = path.read_bytes()
    info = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    with pefile.PE(data=data, fast_load=True) as pe:
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"],
        ])
        info["machine"] = hex(pe.FILE_HEADER.Machine)
        info["managed"] = bool(pe.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)
        info["imports"] = [entry.dll.decode(errors="replace") for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
        info["exports"] = [entry.name.decode(errors="replace") for entry in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []) if entry.name]
        info["version"] = {}
        for tables in getattr(pe, "FileInfo", []):
            for table in tables:
                for strings in getattr(table, "StringTable", []):
                    info["version"].update({k.decode(errors="replace"): v.decode(errors="replace") for k, v in strings.entries.items()})
    if info["managed"]:
        with dnfile.dnPE(str(path), clr_lazy_load=True) as assembly:
            types = getattr(assembly.net.mdtables, "TypeDef", None)
            refs = getattr(assembly.net.mdtables, "AssemblyRef", None)
            info["assembly_references"] = [str(row.Name) for row in refs.rows] if refs else []
            relevant = re.compile(r"export|import|runner|process|dimr|scrip|persist|mdu|boundary|mesh|kernel|serializ", re.I)
            info["interesting_types"] = []
            if types:
                for row in types.rows:
                    name = f"{row.TypeNamespace}.{row.TypeName}"
                    if relevant.search(name):
                        info["interesting_types"].append({"name": name,
                            "methods": [str(index.row.Name) for index in row.MethodList]})
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "evidence" / "installation")
    parser.add_argument("--probe-help", action="store_true")
    args = parser.parse_args()
    install = args.install.resolve(strict=True)
    args.out.mkdir(parents=True, exist_ok=True)
    files = [{"path": p.relative_to(install).as_posix(), "bytes": p.stat().st_size}
             for p in sorted(install.rglob("*")) if p.is_file()]
    (args.out / "files.json").write_text(json.dumps(files, indent=2), encoding="utf-8")
    settings = ET.parse(install / "bin" / "DeltaShell.Gui.exe.config")
    # Whitelist product/runtime settings; do not collect registration/license material.
    keys = {"applicationName", "publicReleaseVersion", "distributionName", "pluginsDirectory", "persistenceDefault", "useNewPersistence"}
    product = {entry.attrib["key"]: entry.attrib.get("value") for entry in settings.findall("./appSettings/add") if entry.attrib.get("key") in keys}
    product["supported_runtime"] = [entry.attrib for entry in settings.findall("./startup/supportedRuntime")]
    product["install"] = str(install)
    product["captured_at_utc"] = datetime.now(timezone.utc).isoformat()
    selected = [install / "bin" / "DeltaShell.Gui.exe", install / "bin" / "DeltaShell.Console.exe"]
    for folder in (install / "plugins").iterdir():
        if any(token in folder.name for token in ["FlowFM", "Dimr", "Scripting", "Persistence", "NetworkEditor", "NGHS", "CommonTools"]):
            selected.extend(folder.glob("*.dll"))
    kernels = install / "plugins" / "DeltaShell.Dimr" / "kernels" / "x64"
    for name in ["dflowfm-cli.exe", "dflowfm.dll", "dimr.exe", "dimr.dll", "io_netcdf.dll", "MeshKernelApi.dll"]:
        selected.extend(kernels.rglob(name))
    binaries = {}
    for path in sorted(set(selected)):
        try:
            binaries[path.relative_to(install).as_posix()] = binary_info(path)
        except Exception as error:
            binaries[path.relative_to(install).as_posix()] = {"error": str(error)}
    (args.out / "binaries.json").write_text(json.dumps(binaries, indent=2), encoding="utf-8")
    launchers = args.out / "launchers"
    launchers.mkdir(exist_ok=True)
    for path in (kernels / "bin").glob("*.bat"):
        (launchers / path.name).write_bytes(path.read_bytes())
    if args.probe_help:
        work = args.out / "help-probes"
        work.mkdir(exist_ok=True)
        history = work / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        history.mkdir()
        environment = os.environ.copy()
        environment["PATH"] = os.pathsep.join(str(kernels / name) for name in ["bin", "lib", "share"]) + os.pathsep + environment.get("PATH", "")
        environment["OMP_NUM_THREADS"] = "1"
        probes = {}
        for executable, option in [("dflowfm-cli.exe", "--help"), ("dflowfm-cli.exe", "--version"), ("dimr.exe", "--help"), ("dimr.exe", "-?"), ("dimr.exe", "-i"), ("DeltaShell.Console.exe", "-?")]:
            key = f"{executable}-{option.lstrip('-')}"
            key = key.replace("?", "usage")
            binary = install / "bin" / executable if executable.startswith("DeltaShell") else kernels / "bin" / executable
            try:
                result = subprocess.run([str(binary), option], cwd=work,
                                        env=environment, capture_output=True, timeout=30)
                (work / f"{key}.stdout.txt").write_bytes(result.stdout)
                (work / f"{key}.stderr.txt").write_bytes(result.stderr)
                (history / f"{key}.stdout.txt").write_bytes(result.stdout)
                (history / f"{key}.stderr.txt").write_bytes(result.stderr)
                probes[key] = {"argv": [str(binary), option],
                               "returncode": result.returncode, "stdout_bytes": len(result.stdout), "stderr_bytes": len(result.stderr)}
            except (OSError, subprocess.TimeoutExpired) as error:
                probes[key] = {"error": str(error)}
        product["help_probes"] = probes
        (history / "probes.json").write_text(json.dumps(probes, indent=2), encoding="utf-8")
    (args.out / "product.json").write_text(json.dumps(product, indent=2), encoding="utf-8")
    print(json.dumps({"product": product, "files": len(files), "binaries_inspected": len(binaries),
                      "binary_errors": {k:v for k,v in binaries.items() if "error" in v}}, indent=2))


if __name__ == "__main__":
    main()
