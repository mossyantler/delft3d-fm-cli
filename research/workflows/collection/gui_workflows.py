"""Read the Korean GUI workflow tables as JSON; the Markdown is authoritative."""

import argparse
import json
from pathlib import Path
import re
import sys


DOCUMENT = Path(__file__).resolve().parents[2] / "notes/collection/gui-workflows.md"
FIELDS = ("operation", "files", "engine", "cli", "evidence")


def inventory(document: str) -> dict:
    refs = dict(re.findall(r"^\[([^\]]+)\]: (\S+)", document, re.M))
    rows = {}
    active = False
    for number, line in enumerate(document.splitlines(), 1):
        if line.startswith("| ID · 작업 |"):
            active = True
            continue
        if not line.startswith("|"):
            active = False
        if not active or line.startswith("| ---"):
            continue
        cells = [s.strip() for s in line.removeprefix("|").removesuffix("|").split("|")]
        if len(cells) != len(FIELDS) or not all(cells):
            raise ValueError(f"line {number}: expected five nonempty fields")
        match = re.fullmatch(r"(?:\*\*)?([A-Z]\d{2}) (.+)", cells[0])
        if not match or match[1] in rows:
            raise ValueError(f"line {number}: missing or duplicate operation ID")
        cells[0] = re.sub(r'\s*<a id="[^"]+"></a>', "", match[2]).removesuffix("**")
        # Expand reference links locally, so a single selected row retains its evidence.
        cells = [re.sub(r"\[([^\]\n]+)\]\[([^\]\n]+)\]",
                        lambda m: f"[{m[1]}]({refs[m[2]]})", cell) for cell in cells]
        rows[match[1]] = {"id": match[1], **dict(zip(FIELDS, cells, strict=True))}
    if not rows:
        raise ValueError("no workflow tables found")
    return rows


def main() -> None:
    rows = inventory(DOCUMENT.read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*", metavar="ID", help="e.g. P04 B02 R02; default: all")
    ids = parser.parse_args().ids
    unknown = set(ids) - rows.keys()
    if unknown:
        parser.error("unknown operation: " + ", ".join(sorted(unknown)))
    selected = [rows[k] for k in ids] if ids else list(rows.values())
    payload = {"document": "research/notes/collection/gui-workflows.md",
               "link_base": "research/notes/collection/", "operations": selected}
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
