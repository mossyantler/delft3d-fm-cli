"""Copy local official PDFs, hash them, and extract page-delimited searchable text.

Extraction is for text search; diagrams and table layout require visual review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from pypdf import PdfReader

from ..paths import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    out = ROOT / "manuals"
    out.mkdir(exist_ok=True)
    manifest = []
    for source in sorted(args.source.glob("*.pdf")):
        target = out / source.name
        if not target.exists():
            shutil.copy2(source, target)
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        copy_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if original_hash != copy_hash:
            raise ValueError(f"Source/copy hash mismatch for {target}")
        reader = PdfReader(target)
        text = target.with_suffix(".txt")
        if not text.exists():
            temporary = text.with_suffix(".txt.partial")
            with temporary.open("w", encoding="utf-8") as stream:
                for number, page in enumerate(reader.pages, 1):
                    stream.write(f"\n\n===== PDF PAGE {number} =====\n\n")
                    stream.write(page.extract_text() or "")
            temporary.replace(text)
        manifest.append({"name": target.name, "original_local_path": str(source.resolve()),
                         "sha256": copy_hash, "pages": len(reader.pages),
                         "metadata": {str(k):str(v) for k,v in (reader.metadata or {}).items()},
                         "text_path": str(text), "visual_layout_verified": False})
        print(f"Indexed {target.name}: {len(reader.pages)} pages", flush=True)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
