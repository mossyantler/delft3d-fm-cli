"""Acquire pinned upstream references and portable analysis tools locally.

No system installation, PATH changes, GUI launches, or driver loading.
The lock file records the exact fetched commits and artifact checksums.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import urllib.request
import zipfile

from ..paths import ROOT
REPOS = {
    "Delft3D": ("Deltares/Delft3D", "DIMRset_2026.02", [
        "doc", "src/engines_gpl/dflowfm", "src/engines_gpl/dimr",
        "src/utils_lgpl/deltares_common", "src/utils_lgpl/ec_module",
        "src/utils_lgpl/io_netcdf", "src/utils_lgpl/gridgeom", "src/scripts_lgpl",
        "src/engines_gpl/wave", "src/engines_gpl/waq", "src/engines_gpl/fbc",
        "src/engines_gpl/rtc", "src/engines_gpl/rr", "src/utils_gpl/morphology",
        "src/utils_gpl/flow1d", "examples/dflowfm/01_dflowfm_sequential",
        "examples/dflowfm/02_dflowfm_parallel"]),
    "HYDROLIB-core": ("Deltares/HYDROLIB-core", None, None),
    "MeshKernel": ("Deltares/MeshKernel", None, None),
    "MeshKernelPy": ("Deltares/MeshKernelPy", None, None),
    "dfm_tools": ("Deltares/dfm_tools", None, None),
    "xugrid": ("Deltares/xugrid", None, None),
}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "delft3d-fm-cli-research"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def clone(name: str) -> dict:
    repo, ref, sparse = REPOS[name]
    target = ROOT / "upstream" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        command = ["git", "clone", "--depth", "1", "--filter=blob:none"]
        if sparse:
            command += ["--no-checkout"]
        if ref:
            command += ["--branch", ref]
        subprocess.run([*command, f"https://github.com/{repo}.git", str(target)], check=True)
        if sparse:
            git(target, "sparse-checkout", "set", "--cone", *sparse)
            git(target, "checkout")
    if not (target / ".git").exists():
        raise RuntimeError(f"Existing destination is not a clone: {target}")
    origin = git(target, "remote", "get-url", "origin")
    if origin != f"https://github.com/{repo}.git":
        raise RuntimeError(f"Unexpected origin for {target}: {origin}")
    if ref and git(target, "rev-parse", "HEAD") != git(target, "rev-parse", f"{ref}^{{commit}}"):
        raise RuntimeError(f"Existing clone does not match requested ref {ref}")
    if sparse:
        git(target, "sparse-checkout", "set", "--cone", *sparse)
    return {"repository": repo, "url": f"https://github.com/{repo}",
            "requested_ref": ref or "default branch at first acquisition",
            "commit": git(target, "rev-parse", "HEAD"),
            "origin": origin,
            "path": str(target), "sparse_paths": sparse,
            "scope": "research reference; dependency compatibility not yet validated"}


def download_tool(name: str, url: str, digest: str | None = None) -> dict:
    target = ROOT / "tools" / name
    target.mkdir(parents=True, exist_ok=True)
    archive = target / url.rsplit("/", 1)[-1]
    if not archive.exists():
        payload = fetch(url)
        temporary = archive.with_suffix(archive.suffix + ".partial")
        temporary.write_bytes(payload)
        temporary.replace(archive)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest and digest != f"sha256:{sha}":
        raise ValueError(f"Publisher digest mismatch for {archive}")
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (target / member.filename).resolve().is_relative_to(target.resolve()):
                raise ValueError(f"Unsafe archive path: {member.filename}")
        package.extractall(target)
    return {"url": url, "archive": str(archive), "sha256": sha,
            "publisher_digest": digest, "publisher_digest_verified": bool(digest),
            "status": "downloaded and extracted; not launched"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["repo", "tools"])
    parser.add_argument("name", nargs="?", choices=list(REPOS))
    args = parser.parse_args()
    (ROOT / "evidence" / "acquisition").mkdir(parents=True, exist_ok=True)
    if args.kind == "repo":
        if not args.name:
            parser.error("repo requires a name")
        record = clone(args.name)
        name = args.name
    else:
        record = {
            "process-monitor": download_tool("process-monitor", "https://download.sysinternals.com/files/ProcessMonitor.zip"),
            "strings": download_tool("strings", "https://download.sysinternals.com/files/Strings.zip"),
        }
        for repo, name, select in [
            ("icsharpcode/ILSpy", "ilspy", lambda n: "selfcontained" in n.lower() and n.endswith("-x64.zip") and "windows" in n.lower()),
            ("lucasg/Dependencies", "dependencies", lambda n: n == "Dependencies_x64_Release.zip"),
        ]:
            release = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest"))
            matches = [a for a in release["assets"] if select(a["name"])]
            if len(matches) != 1:
                raise RuntimeError(f"Cannot select a unique asset for {repo}")
            asset = matches[0]
            record[name] = download_tool(name, asset["browser_download_url"], asset.get("digest"))
            record[name]["release"] = release["tag_name"]
        name = "tools"
    record["acquired_at_utc"] = datetime.now(timezone.utc).isoformat()
    (ROOT / "evidence" / "acquisition" / f"{name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
