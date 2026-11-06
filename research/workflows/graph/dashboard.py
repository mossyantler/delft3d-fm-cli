"""Local Beads dashboard through beads_viewer (bv) (GRAPH-OPS-VIEWER).

From any checkout or worktree of this repository:

    python -m research.workflows.graph.dashboard pages     # build the static HTML dashboard
    python -m research.workflows.graph.dashboard preview   # serve it on http://127.0.0.1:9000 (Ctrl+C stops)
    python -m research.workflows.graph.dashboard tui       # interactive terminal viewer

bv only ever reads a **copy** of the issue export, placed in
``<main checkout>-beads/dashboard/source/issues.jsonl``. That directory is outside the
repository and outside the Dolt workspace. bv runs from that directory without bd on
PATH or any Beads variables, so its edit-save path has no writable tracker to use.
The source is a fresh ``bdw export`` when ``DFM_BD_ROLE=coordinator``; anyone else
gets ``research/notes/delivery/beads-state.jsonl`` as committed at the main checkout's
HEAD (never the working-tree file), which reflects the last ``backup-sync``.
Hooks and bv's update check are off.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from research.workflows.graph import bdw

BV_VERSION = "0.25.2"
BV_SHA256 = "6ed65731cbee1a4407b360aa0ff00bfe72f7cf13a524bf66c75c6a7db8b381e1"
TRACKER_STEMS = ("bd", "br")  # any extension: bd.exe, bd.cmd, br.bat, bd.ps1, ... (VIEWER-V-001)


def holds_tracker(entry: str) -> bool:
    try:
        with os.scandir(entry) as it:
            return any(Path(e.name).stem.lower() in TRACKER_STEMS and e.is_file() for e in it)
    except OSError:
        return False


def bv_exe(main: Path, environ: dict[str, str]) -> Path:
    exe = Path(environ.get("DFM_BV_EXE") or main / "research" / "tools" / "bv" / BV_VERSION / "bv.exe").resolve()
    if not exe.is_file():
        raise bdw.Refused(f"bv {BV_VERSION} not found at {exe}; see research/notes/collection/toolbox.md")
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    if digest != BV_SHA256:
        raise bdw.Refused(f"bv binary SHA-256 {digest} does not match the pinned {BV_SHA256}")
    return exe


def viewer_env(environ: dict[str, str]) -> dict[str, str]:
    """Environment without Beads/bv settings and without any PATH entry holding a tracker CLI."""
    env = {k: v for k, v in environ.items() if not k.upper().startswith(("BD_", "BEADS_", "BV_", "DFM_"))}
    path_key = next((k for k in env if k.upper() == "PATH"), "PATH")
    entries = [p for p in env.get(path_key, "").split(os.pathsep) if p and not holds_tracker(p)]
    env[path_key] = os.pathsep.join(entries)
    env["BV_NO_UPDATE_CHECK"] = "1"
    return env


def prepare(cwd: Path, environ: dict[str, str]) -> tuple[Path, Path, dict]:
    paths = bdw.derive_paths(cwd, environ)
    exe = bv_exe(paths.main, environ)
    root = paths.beads_dir.parent / "dashboard"
    source = root / "source" / "issues.jsonl"
    source.parent.mkdir(parents=True, exist_ok=True)
    if bdw.role_of(environ) == "coordinator":
        p = subprocess.run([sys.executable, "-m", "research.workflows.graph.bdw", "export", "-o", str(source)],
                           cwd=paths.main, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode:
            raise bdw.Refused(f"bdw export failed: {p.stderr.strip() or p.stdout.strip()}")
        origin = "fresh bdw export"
    else:
        # The blob at the main checkout's HEAD, not the working-tree file (VIEWER-V-002).
        rel = bdw.JSONL_REL.as_posix()
        p = subprocess.run(["git", "--no-optional-locks", "show", f"HEAD:{rel}"], cwd=paths.main,
                           capture_output=True)
        if p.returncode:
            raise bdw.Refused(f"{rel} is not committed at HEAD of {paths.main}; the coordinator runs bdw backup-sync")
        source.write_bytes(p.stdout)
        origin = f"committed HEAD:{rel}"
    info = {"source": str(source), "origin": origin,
            "issues": sum(1 for line in source.read_text(encoding="utf-8").splitlines() if line.strip()),
            "bv": str(exe)}
    return exe, root, info


def run_bv(exe: Path, root: Path, args: list[str], environ: dict[str, str], capture: bool) -> subprocess.CompletedProcess:
    argv = [str(exe), "--db", str(root / "source" / "issues.jsonl"), *args]
    return subprocess.run(argv, cwd=root, env=viewer_env(environ), capture_output=capture, text=capture,
                          encoding="utf-8" if capture else None, errors="replace" if capture else None)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = dict(os.environ)
    try:
        if argv == ["pages"]:
            exe, root, info = prepare(Path.cwd(), environ)
            site = root / "site"
            if site.exists():
                shutil.rmtree(site)
            p = run_bv(exe, root, ["--no-hooks", "--export-pages", str(site), "--pages-include-history=false",
                                   "--pages-title", "delft3d-fm-cli 공정"], environ, capture=True)
            info.update(site=str(site / "index.html"), exit=p.returncode, log=(p.stdout + p.stderr).strip()[-1500:])
            print(json.dumps(info, indent=1, ensure_ascii=False))
            return p.returncode
        if argv == ["preview"]:
            exe, root, info = prepare(Path.cwd(), environ)
            if not (root / "site" / "index.html").is_file():
                raise bdw.Refused("no site yet; run `dashboard pages` first")
            return run_bv(exe, root, ["--preview-pages", str(root / "site")], environ, capture=False).returncode
        if argv == ["tui"]:
            exe, root, info = prepare(Path.cwd(), environ)
            return run_bv(exe, root, [], environ, capture=False).returncode
        print(__doc__)
        return 2
    except bdw.Refused as exc:
        print(json.dumps({"refused": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
