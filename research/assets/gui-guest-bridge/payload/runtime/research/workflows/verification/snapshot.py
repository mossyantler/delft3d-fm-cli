"""Hash an experiment folder before/after ONE GUI action, or compare snapshots."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def snapshot(root: Path, output: Path) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Snapshot root must be a directory")
    output = output.resolve()
    files, errors = {}, []
    for path in sorted(root.rglob("*")):
        if path.resolve() == output or path.is_symlink():
            continue
        if path.is_file():
            try:
                before = path.stat()
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError("file changed during snapshot")
                files[path.relative_to(root).as_posix()] = {"bytes": after.st_size,
                    "mtime_ns": after.st_mtime_ns, "sha256": digest.hexdigest()}
            except (OSError, RuntimeError) as error:
                errors.append({"path": str(path), "error": str(error)})
    return {"root": str(root), "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "files": files, "errors": errors, "complete": not errors}


def compare(before: dict, after: dict) -> dict:
    a, b = before["files"], after["files"]
    return {"before_root": before["root"], "after_root": after["root"],
            "added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
            "content_changed": sorted(k for k in a.keys() & b.keys() if a[k]["sha256"] != b[k]["sha256"]),
            "metadata_only": sorted(k for k in a.keys() & b.keys() if a[k]["sha256"] == b[k]["sha256"] and a[k] != b[k]),
            "complete": before.get("complete", False) and after.get("complete", False)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    take = commands.add_parser("take")
    take.add_argument("root", type=Path)
    take.add_argument("--out", required=True, type=Path)
    diff = commands.add_parser("diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument("--out", type=Path)
    args = parser.parse_args()
    data = snapshot(args.root, args.out) if args.command == "take" else compare(
        json.loads(args.before.read_text(encoding="utf-8")), json.loads(args.after.read_text(encoding="utf-8")))
    encoded = json.dumps(data, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    print(encoded if args.command == "diff" else json.dumps({"files": len(data["files"]), "errors": data["errors"], "output": str(args.out)}))
    if not data["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
