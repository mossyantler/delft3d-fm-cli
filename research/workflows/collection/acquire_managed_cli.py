"""Acquire isolated ILSpyCmd and matching portable .NET runtime from publishers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from .acquire import ROOT, fetch, download_tool


def main() -> None:
    base = "https://api.nuget.org/v3-flatcontainer/ilspycmd"
    versions = json.loads(fetch(base + "/index.json"))["versions"]
    version = [v for v in versions if "-" not in v][-1]
    tool = download_tool("ilspycmd", f"{base}/{version}/ilspycmd.{version}.nupkg")
    directory = ROOT / "tools" / "ilspycmd"
    settings = list(directory.glob("tools/*/*/DotnetToolSettings.xml"))
    if len(settings) == 1:
        rid = ET.parse(settings[0]).find("./RuntimeIdentifierPackages/RuntimeIdentifierPackage[@RuntimeIdentifier='win-x64']")
        if rid is not None:
            package = rid.attrib["Id"].lower()
            tool["rid_package"] = download_tool("ilspycmd-win-x64", f"https://api.nuget.org/v3-flatcontainer/{package}/{version}/{package}.{version}.nupkg")
            directory = ROOT / "tools" / "ilspycmd-win-x64"
    configs = list(directory.rglob("ilspycmd.runtimeconfig.json"))
    executables = list(directory.rglob("ilspycmd.exe"))
    if not configs and len(executables) == 1:
        record = {"ilspycmd": tool, "version": version, "command": [str(executables[0])],
                  "runtime": "native/self-contained package; no separate runtime acquisition"}
        out = ROOT / "evidence" / "acquisition" / "managed-cli.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))
        return
    if len(configs) != 1:
        raise RuntimeError("Cannot select ILSpyCmd runtime config")
    config = json.loads(configs[0].read_text(encoding="utf-8"))
    framework = config["runtimeOptions"]["framework"]
    channel = ".".join(framework["version"].split(".")[:2])
    metadata_url = f"https://builds.dotnet.microsoft.com/dotnet/release-metadata/{channel}/releases.json"
    releases = json.loads(fetch(metadata_url))
    release = next(r for r in releases["releases"] if r["runtime"]["version"] == releases["latest-runtime"])
    asset = next(a for a in release["runtime"]["files"] if a["rid"] == "win-x64" and a["name"].endswith(".zip"))
    # Acquire runtime without extraction until the publisher SHA-512 is verified.
    runtime_dir = ROOT / "tools" / "dotnet-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    archive = runtime_dir / asset["url"].rsplit("/", 1)[-1]
    if not archive.exists():
        archive.write_bytes(fetch(asset["url"]))
    payload = archive.read_bytes()
    if hashlib.sha512(payload).hexdigest().lower() != asset["hash"].lower():
        raise ValueError(".NET runtime publisher SHA-512 mismatch")
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (runtime_dir / member.filename).resolve().is_relative_to(runtime_dir.resolve()):
                raise ValueError("Unsafe runtime archive path")
        package.extractall(runtime_dir)
    record = {"ilspycmd": tool, "version": version, "runtime_config": config,
        "runtime": {"url": asset["url"], "sha512": asset["hash"], "publisher_digest_verified": True,
                    "version": release["runtime"]["version"], "path": str(runtime_dir), "metadata_url": metadata_url},
        "command": [str(runtime_dir / "dotnet.exe"), str(configs[0].with_name("ilspycmd.dll"))]}
    out = ROOT / "evidence" / "acquisition" / "managed-cli.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
