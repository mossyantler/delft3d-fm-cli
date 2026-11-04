from __future__ import annotations

import os
from pathlib import Path
import xml.etree.ElementTree as ET

from .common import DfmError, sha

LAYOUT = "plugins/DeltaShell.Dimr/kernels/x64"


def discover(roots: list[str]) -> dict:
    candidates = []
    if os.environ.get("DFM_INSTALL"):
        candidates.append(Path(os.environ["DFM_INSTALL"]))
    folders = [Path(p) for p in roots] if roots else [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Deltares"]
    for root in folders:
        if root.is_dir():
            candidates.extend([root, *[p for p in root.iterdir() if p.is_dir()]])
    found = sorted({str(p.resolve()) for p in candidates if (p / LAYOUT / "bin/dflowfm-cli.exe").is_file()})
    return {"installations": found, "searched_roots": [str(p) for p in folders],
            "scope": "Explicit roots and their immediate children; DFM_INSTALL; known Windows x64 suite layout"}


def inspect(root: Path) -> dict:
    root = root.resolve(strict=True)
    kernels = root / LAYOUT
    binaries = {}
    for name in ["bin/dflowfm-cli.exe", "bin/dimr.exe", "lib/dflowfm.dll", "lib/dimr.dll", "lib/gdal.dll"]:
        item = kernels / name
        binaries[name] = {"path": str(item), "exists": item.is_file(), "sha256": sha(item) if item.is_file() else None}
    product = {}
    config = root / "bin/DeltaShell.Gui.exe.config"
    if config.is_file():
        try:
            for entry in ET.parse(config).findall("./appSettings/add"):
                if entry.get("key") in {"applicationName", "publicReleaseVersion", "distributionName"}:
                    product[entry.get("key")] = entry.get("value")
        except ET.ParseError as exc:
            raise DfmError("installation_config", "Cannot parse suite configuration", details=str(exc)) from exc
    db = root / "bin/gdal/share/proj.db"
    return {"root": str(root), "kernels": str(kernels), "product": product, "binaries": binaries,
            "proj_data": str(db.parent) if db.is_file() else None,
            "capabilities": {"direct_binary_present": binaries["bin/dflowfm-cli.exe"]["exists"],
                             "dimr_binary_present": binaries["bin/dimr.exe"]["exists"],
                             "validated_reference": "E004/E008: 2026.02 OpenHMWQ, f34 short serial; other versions unverified"},
            "engine_version": None, "source_revision": None,
            "limitations": ["Presence/hash inspection only; no native execution or complete DLL dependency resolution"]}


def select(value: str | None) -> dict:
    value = value or os.environ.get("DFM_INSTALL")
    if value:
        return inspect(Path(value))
    found = discover([])["installations"]
    if len(found) != 1:
        raise DfmError("installation_required", "Specify --install or DFM_INSTALL when discovery does not yield exactly one installation", details=found)
    return inspect(Path(found[0]))
