"""Build provenance locks and searchable candidate MDU keys from collected source."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from ..paths import ROOT


def main() -> None:
    lock = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "repositories": {}, "tools": {}}
    for record in sorted((ROOT / "evidence/acquisition").glob("*.json")):
        data = json.loads(record.read_text(encoding="utf-8"))
        if "repository" in data:
            lock["repositories"][record.stem] = data
        else:
            lock["tools"][record.stem] = data
    (ROOT / "sources.lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    source = ROOT / "upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90"
    text = source.read_text(encoding="utf-8", errors="replace")
    pattern = r"call\s+prop_set\(\s*prop_ptr\s*,\s*'([^']+)'\s*,\s*'([^']+)'"
    keys = [{"section": m[1], "key": m[2], "line": text.count("\n", 0, m.start())+1} for m in re.finditer(pattern, text, re.I)]
    models = ROOT / "upstream/HYDROLIB-core/hydrolib/core/dflowfm/mdu/models.py"
    model_text = models.read_text(encoding="utf-8")
    classes = []
    for node in ast.parse(model_text).body:
        if isinstance(node, ast.ClassDef):
            fields = [{"name": field.target.id, "annotation": ast.unparse(field.annotation), "line": field.lineno}
                      for field in node.body if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)]
            classes.append({"class": node.name, "line": node.lineno, "fields": fields})
    out = ROOT / "catalog"
    out.mkdir(exist_ok=True)
    catalog = {"scope": "Candidate literal prop_set keys and Python annotated fields; not a complete engine schema. Defaults, dynamic sections, aliases, and semantic constraints require source review.",
               "engine_commit": lock["repositories"]["Delft3D"]["commit"],
               "engine_source": source.relative_to(ROOT).as_posix(), "engine_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "engine_candidate_keys": keys,
               "hydrolib_commit": lock["repositories"]["HYDROLIB-core"]["commit"],
               "hydrolib_source": models.relative_to(ROOT).as_posix(), "hydrolib_classes": classes}
    (out / "mdu-candidates.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(json.dumps({"repositories": len(lock["repositories"]), "engine_candidate_keys": len(keys),
                      "hydrolib_classes": len(classes), "hydrolib_annotated_fields": sum(len(c["fields"]) for c in classes)}))


if __name__ == "__main__":
    main()
