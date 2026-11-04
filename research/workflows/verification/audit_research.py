"""Verify collected provenance, local artifacts, source links and snapshot behavior."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

from ..paths import ROOT
from .snapshot import snapshot, compare


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    checks = []
    lock = json.loads((ROOT / "sources.lock.json").read_text(encoding="utf-8"))
    for name, record in lock["repositories"].items():
        path = ROOT / "upstream" / name
        actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        assert actual == record["commit"], (name, actual, record["commit"])
        checks.append(f"repository commit: {name}")
    for record in sorted((ROOT / "evidence/acquisition").glob("*.json")):
        data = json.loads(record.read_text(encoding="utf-8"))
        def visit(value):
            if isinstance(value, dict):
                if "archive" in value and "sha256" in value:
                    assert sha(Path(value["archive"])) == value["sha256"], value["archive"]
                    checks.append(f"artifact SHA-256: {Path(value['archive']).name}")
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(data)
    manuals = json.loads((ROOT / "manuals/manifest.json").read_text(encoding="utf-8"))
    for manual in manuals:
        assert sha(ROOT / "manuals" / manual["name"]) == manual["sha256"]
        assert Path(manual["text_path"]).stat().st_size > 0
        assert len(re.findall(r"^===== PDF PAGE \d+ =====$", Path(manual["text_path"]).read_text(encoding="utf-8"), re.M)) == manual["pages"], manual["name"]
        checks.append(f"manual SHA-256/text: {manual['name']}")
    candidates = json.loads((ROOT / "catalog/mdu-candidates.json").read_text(encoding="utf-8"))
    assert sha(ROOT / candidates["engine_source"]) == candidates["engine_source_sha256"]
    assert candidates["engine_commit"] == lock["repositories"]["Delft3D"]["commit"]
    assert candidates["hydrolib_commit"] == lock["repositories"]["HYDROLIB-core"]["commit"]
    checks.append("MDU candidate index source provenance")
    managed = json.loads((ROOT / "evidence/managed-inspection/manifest.json").read_text(encoding="utf-8"))
    for name, record in managed.items():
        assert record["returncode"] == 0 and record["stderr_bytes"] == 0, name
        assert sha(Path(record["assembly"])) == record["assembly_sha256"], name
        assert (ROOT / "evidence/managed-inspection" / f"{name}.cs").stat().st_size > 0
    checks.append(f"targeted managed inspection: {len(managed)} types")
    for doc in [ROOT.parent / "AGENTS.md", ROOT.parent / "README.md", ROOT / "README.md", *sorted((ROOT / "notes").rglob("*.md"))]:
        for link in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            if "://" not in link and not link.startswith("#"):
                assert (doc.parent / link.split("#", 1)[0]).exists(), (doc, link)
    checks.append("local documentation links")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "evidence" / "verification" / stamp
    model = folder / "fixture"
    model.mkdir(parents=True)
    for name in ["keep.txt", "edit.txt", "removed.txt"]:
        (model / name).write_text("before", encoding="utf-8")
    before = snapshot(model, folder / "before.json")
    (model / "edit.txt").write_text("after", encoding="utf-8")
    (model / "added.txt").write_text("added", encoding="utf-8")
    removed = (model / "removed.txt").resolve()
    assert removed.is_relative_to(model.resolve())
    removed.unlink()
    after = snapshot(model, folder / "after.json")
    delta = compare(before, after)
    assert delta["complete"]
    assert delta["added"] == ["added.txt"]
    assert delta["removed"] == ["removed.txt"]
    assert delta["content_changed"] == ["edit.txt"]
    assert compare(after, after)["content_changed"] == []
    checks.append("snapshot detects additions/removals/edits and unchanged inputs")
    for path in ROOT.rglob("*.json"):
        if "upstream" not in path.parts and "tools" not in path.parts and ".venv" not in path.parts:
            json.loads(path.read_text(encoding="utf-8-sig"))
    checks.append("project-generated JSON parses")
    report = {"status": "passed", "checks": checks, "manuals": len(manuals),
              "manual_pdf_pages": sum(m["pages"] for m in manuals), "managed_types": len(managed),
              "scope": "artifact/provenance and investigation utility checks; no simulation or physical validation"}
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
