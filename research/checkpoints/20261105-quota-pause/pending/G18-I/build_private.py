"""File-only private root191 composition and clean wheel install. No solver."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(data): return hashlib.sha256(data).hexdigest()
def dump(name, value): (HERE/name).write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")
def inventory(root): return {p.relative_to(root).as_posix(): {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and not p.suffix == ".pyc"}


def run(label, argv, cwd):
    env = dict(os.environ); env.pop("PYTHONPATH", None); env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, capture_output=True, timeout=180)
    (HERE/(label+".stdout.txt")).write_bytes(result.stdout); (HERE/(label+".stderr.txt")).write_bytes(result.stderr)
    dump(label+".json", {"argv": list(map(str, argv)), "cwd": str(cwd), "returncode": result.returncode})
    if result.returncode: raise RuntimeError(label+" failed; retained logs")
    return result.stdout


def main():
    if sys.argv[1:] == ["--resume-file-only-build"]:
        package = HERE/"package"
        if inventory(package/"src/dfm_cli") != json.loads((HERE/"candidate196.json").read_text()): raise RuntimeError("Package changed")
        finish(package, "retry-")
        return
    base = inventory(ROOT/"src/dfm_cli")
    if len(base) != 191: raise RuntimeError("Expected reviewed root191, no implicit composition")
    if (HERE/"package").exists(): raise RuntimeError("Fresh build only")
    dump("root191-before.json", base)
    package = HERE/"package"; package.mkdir()
    shutil.copytree(ROOT/"src/dfm_cli", package/"src/dfm_cli", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(ROOT/"pyproject.toml", package/"pyproject.toml")
    patches = []
    for name in ("section_orientation.py", "cli.py"):
        path = package/"src/dfm_cli"/name; original = path.read_bytes(); data = original
        if name == "section_orientation.py":
            changes = [(b"    return actions", b"    from . import section_transfer\n    section_transfer.register(actions)\n    return actions"),
                       (b"def execute(args):", b"def execute(args):\n    if args.action in (\"export\", \"import\"):\n        from . import section_transfer\n        return section_transfer.execute(args)")]
        else:
            changes = [(b"from . import boundary_support,", b"from . import section_transfer\nfrom . import boundary_support,"),
                       (b'                "section_orientation": section_orientation.contract(),', b'                "section_orientation": section_orientation.contract(),\n                "section_transfer": section_transfer.contract(),')]
        # Match source tokens without renormalizing unrelated CRLF/LF bytes.
        eol = b"\r\n" if b"\r\n" in original else b"\n"
        for old, new in changes:
            if data.count(old) != 1: raise RuntimeError("Ambiguous integration token: "+name)
            data = data.replace(old, new.replace(b"\n", eol), 1)
        path.write_bytes(data)
        patches.extend(difflib.unified_diff(original.decode().splitlines(True), data.decode().splitlines(True), fromfile="a/src/dfm_cli/"+name, tofile="b/src/dfm_cli/"+name))
    for path in (HERE/"src/dfm_cli").glob("*.py"): shutil.copyfile(path, package/"src/dfm_cli"/path.name)
    (HERE/"integration.patch").write_text("".join(patches), encoding="utf-8", newline="")
    candidate = inventory(package/"src/dfm_cli"); dump("candidate196.json", candidate)
    if len(candidate) != 196: raise RuntimeError("Expected exactly5 additive modules")
    modified = [p for p in base if base[p] != candidate[p]]
    if modified != ["cli.py", "section_orientation.py"]: raise RuntimeError("Unexpected base delta: "+str(modified))
    dump("filedelta.json", {"base_files": 191, "candidate_files": 196, "unchanged_base": 189, "modified": modified, "added": sorted(set(candidate)-set(base))})
    finish(package, "")
    after = inventory(ROOT/"src/dfm_cli"); dump("root191-after-build.json", after)
    if after != base: raise RuntimeError("Concurrent root source delta; candidate retained, do not label current root identical")


def finish(package, prefix):
    run(prefix+"build-wheel", [sys.executable, "-I", "-B", "-m", "pip", "--isolated", "wheel", "--no-deps", "--wheel-dir", HERE/"wheel", package], package)
    wheel, = (HERE/"wheel").glob("*.whl")
    run(prefix+"create-venv", [sys.executable, "-B", "-m", "venv", HERE/"venv"], HERE)
    python = HERE/"venv/Scripts/python.exe" if os.name == "nt" else HERE/"venv/bin/python"
    run(prefix+"install-wheel", [python, "-I", "-m", "pip", "install", "--no-deps", wheel], HERE)
    dump("installed-wheel.json", {"wheel": str(wheel), "sha256": sha(wheel.read_bytes()), "bytes": wheel.stat().st_size, "python": str(python), "dfm": str(python.with_name("dfm.exe" if os.name == "nt" else "dfm"))})
    run(prefix+"schema", [python, "-I", "-B", "-m", "dfm_cli", "schema", "inspect"], HERE)


if __name__ == "__main__": main()
