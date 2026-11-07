"""Read-only legacy inventory, never a migration of the operational database.

python -m research.workflows.graph.compat --snapshot <export.jsonl>
The output is a deterministic dry-run report; original bytes/hash and original
records stay unchanged. No missing identity or approval is inferred.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.workflows.graph import protocol


def inventory(path: Path) -> dict:
    raw = path.read_bytes()
    records = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        issue = json.loads(line)
        meta = issue.get("metadata") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        receipt = meta.get("receipt")
        if isinstance(receipt, dict) and receipt.get("schema_version") != protocol.VERSION:
            records.append({"id": issue.get("id"), "line": number,
                "original_line_sha256": protocol.digest(line.encode("utf-8")),
                "interpretation": protocol.legacy_interpretation(receipt),
                "action": "preserve; explicit target/evidence review needed only for new gates"})
    return {"dry_run": True, "source_sha256": protocol.digest(raw), "writes": 0, "records": records,
            "changes_approvals": False, "changes_lifecycle": False,
            "requires_review": ["dispatch binding", "candidate", "Contract", "plan", "artifacts", "approval scope"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(inventory(args.snapshot), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
